# The tactical map

Operator, 2026-10-21: "there will need to be a serious system made for this where in addition to seeing the camera out
crisp while we're playing the game, we might need to hack the game using hooks to have a second camera where we're
looking at the view from top down in order to have a more manageable experience. When it comes to game hookingness, I
want Chris to have an awareness of where the nearest time bonus is and to be able to navigate to it, get it, look at
the time, and be able to make a stand according to the time."

A live top-down view of a Mercenaries round sits beside the game's stream in the Sessions view (the "Tactical map"
section of the side column; drag it under the game like the other sections). gBox draws it from the game's own state
in RAM: the stage's navmesh, the player (Chris, Barry, whoever was picked), the Majini, the hourglasses, and what the bot means to do.

**Why not a second in-game camera.** A second viewport hooked into the game would have to live inside RPCS3's
recompiled PPU code, which is the riskiest place to patch. Turning the game's own camera overhead would also break the
bot's aim, because the RE5 bot closes its aim loop on the camera's look ray (`re5_ps3.Bot`, `snap["camera"]`). Drawing
the map from RAM in gBox costs the game nothing and shows the whole stage, including what the camera can't see. The
optional overhead camera is evaluated under "An overhead camera in the game" below.

## What it shows

- **Stage.** The navmesh's floor, shaded by level: the player's level (within 1.5 m of his height) is brightest, the levels
  above and below are dimmer. It shows the walls (mesh edges that nothing walks across) and the ladders and drops
  (near-vertical triangles: `climbs`).
- **The player.** An arrow along his facing, with a 12 m aim line while he aims.
- **Majini.**
  - A filled dot means alive. A hollow dot means out of his line of sight (`no_los`).
  - A ring means attacking. A dashed green ring means in the way of his route (`blocking`).
  - Crosshair ticks mark the bot's target.
  - Faded with a ▲ or ▼: on another level.
- **Hourglasses.**
  - A time bonus has its own glyph; a ring around it marks a combo bonus.
  - A hollow one has been taken, and it stays on the map until the round ends.
  - The nearest one is labelled with its route distance and ETA. When it is off the map, an arrow at the edge points
    to it.
- **Plan.** The bot's route (dashes from the player), its stand spot (a ringed flag) and a non-enemy target (crosshair).
- **Above the map.**
  - The round clock, score and kills.
  - Combo ×N with its window, and the bot's phase (Gather time, Combo bonus, Stand, Break for time).
  - The nearest bonus ("Time bonus · 29 m · ~6.5 s"; `~` marks an estimate) and the target.
  - Between rounds it says where the game is, and it says when the frames stopped.
- **Views.** Follow keeps the player and goal in view; Stage fits the stage. Heading up turns with the player.
  Hover holds the current centre, rotation and scale while live actors continue updating. The wheel zooms about
  the cursor, and primary-button dragging pans. Manual views remain held until Follow or Stage is selected.
- **Collection commands.** Click an available time/combo bonus or a verified recovery item to request collection.
  The status names the queued, active or deferred goal, and Cancel goal releases it. A drag sends no command.
  Recovery items have a green cross. Other unknown ground objects are not offered as collectable items.

Colors (checked for color-vision deficiency with the dataviz validator, light and dark):

| | light | dark |
|---|---|---|
| Player | blue `#2a78d6` | `#3987e5` |
| Majini | red `#e34948` | `#e34948` |
| Bonus | yellow `#eda100` | `#c98500` |
| Plan | green `#1baf7a` | `#199e70` |

Every mark also differs by shape (arrow, dot, hourglass, dashes, ring), so no meaning rides on color alone.

## Contract `gbox.tactical/1`

There are two JSON payloads. World units are the title's own (RE5 `cm`, RE4 `mm`), with y up. Headings are radians in
the engines' `atan2(dx, dz)` convention (0 = +z, positive toward +x). Seen from above, +z is up and +x is to the
**left**: the worlds are right-handed with y up (facing +z, +x is on the player's left), so `view` says
`{"x": -1, "z": 1}`.

### Frame

One frame per engine tick, at most 10 a second; the newest wins. It is about 1.5 KB with 12 Majini and 9 hourglasses.

```json
{"v": 1, "t": 1792586498.89, "title": "BLUS30491", "stage": "BLUS30491.nav2187.f121d3db", "units": "cm",
 "screen": "playing",
 "clock": {"left": 46.92, "start": 120.0, "combo": 3, "combo_left": 8.75, "score": 2720, "kills": 7},
 "player": {"pos": [-1688, 202, -3754], "facing": 1.54, "hp": 706, "hp_max": 1000, "state": "aim", "aim": true},
 "enemies": [{"id": 3, "pos": [-1436, 215, -3091], "hp": 800, "hp_max": 800, "flags": ["attacking", "target"]}],
 "bonuses": [{"id": 810055344, "pos": [-2087, 269, -1744], "kind": "time", "taken": false}],
 "plan": {"phase": "gather_time", "target": {"kind": "bonus", "id": 810055344, "pos": [-2087, 269, -1744]},
          "route": [[-1500, 200, -3300], [-2087, 269, -1744]], "stand": {"pos": [-200, 60, -400], "r": 300},
          "nearest_bonus": {"id": 810055344, "kind": "time", "pos": [-2087, 269, -1744], "dist": 2867, "eta_s": 6.4},
          "note": "short text"}}
```

- `screen` is the engine's screen (`playing`, `dead`, `paused`, `results`, `loading`, the menus' names, or `stopped`
  when the autoplay ended). Between rounds there is no `player`, and the round's hourglasses are forgotten.
- `enemies` are the living ones. The dead and the crows (1 health) are left out. `flags` come from the plan's
  `enemy_flags`, plus `target`.
- `bonuses` keep the taken ones (`"taken": true`) for the rest of the round.
- `plan` is optional. Its keys are listed under "From the bot".

### Stage

The stage is sent once per stage key and never changes under that key. The key is the title, the triangle count and a
CRC of the points (`BLUS30491.nav2187.f121d3db`), so a stage keeps its key across rounds, restarts and PCs. Public
Assembly is about 62 KB.

```json
{"v": 1, "key": "BLUS30491.nav2187.f121d3db", "title": "BLUS30491", "units": "cm", "kind": "mesh",
 "view": {"x": -1, "z": 1}, "bounds": [-2819, -3990, 2980, 3050], "y": [-200, 938],
 "points": [x, y, z, ...], "tris": [a, b, c, ...], "walls": [a, b, ...], "cross": [a, b, ...],
 "climbs": [[x, z, y_low, y_high], ...]}
```

- `walls` are the triangle edges with no link across them.
- `cross` holds edges whose link goes to a triangle that doesn't share both ends (a jump). RE5's mesh has none: its
  ladders and drops are steep triangles, listed in `climbs`.
- `kind: "grid"` is reserved for a title whose stage is a raster (RE4's `re4_navmap` grid).

### Routes (control plane, `gbox/tactical_map.py`)

| route | what |
|---|---|
| `POST /api/autoplay/tactical/{sid}` | a frame → `{"ok", "seq", "need_stage"}` |
| `GET /api/autoplay/tactical/{sid}?after=N` | the newest frame, with `seq`, `age_s` and `live` (younger than 3 s). Returns `{"seq", "same": true, "age_s", "live"}` when N is already the newest, and `{}` when nothing came for 10 min |
| `PUT /api/autoplay/tactical/stage/{key}` | a stage |
| `GET /api/autoplay/tactical/stage/{key}` | that stage, or 404 |

The live server's frames and stages are held in memory only. RE5 also retains local navigation evidence as described below. After a restart, the next frame's reply says
`need_stage` and the worker sends the stage again. Limits are 64 KB per frame and 4 MB per stage, with 24 stages kept.

### From the bot: `plan()`

A title's brain may have `plan() -> dict`. The publisher calls it on the engine's thread at the start of each tick
it keeps, so it reflects the bot's last decision. It must be cheap: no RAM reads, only what the bot already holds.
Every key is optional:

```python
{"phase": "gather_time" | "combo_bonus" | "stand" | "break_for_time",
 "target": {"kind": "enemy" | "bonus" | "stand" | "waypoint", "id": slot_or_ptr, "pos": (x, y, z)},
 "route": [(x, y, z), ...],                 # the waypoints still ahead, the next first
 "stand": {"pos": (x, y, z), "r": units},   # the planned stand spot
 "nearest_bonus": {"id": ptr, "kind": "time" | "combo", "dist": units_along_the_route, "eta_s": seconds},
 "enemy_flags": {slot: ["attacking", "blocking", "no_los"]},
 "note": "<= 80 chars"}
```

A brain without `plan()` still gets a map:

- The target and route come from `bot.target` and `bot.route`.
- The nearest bonus is found by the navmesh's route length (A*, at most once a second, for the three nearest in a
  straight line) at 4.5 m/s, and is marked `"est": true`.

## How it flows

- **Engine.** `gbox/mercs/engine.play_round(..., tactical=)` hands `(snap, bot, screen)` to the hook every tick.
- **Publisher.** The hook is a `Publisher` (`gbox/mercs/tactical.py`):
  - It keeps at most 10 frames a second and takes `bot.plan()` on the engine's thread.
  - It builds and posts each frame on its own thread, the newest winning. A slow or absent control plane never costs
    the round a tick: after a failed post it backs off for a few seconds.
  - Between rounds, `mercs_bot.play` sends the screen once a second. When the run ends, it posts `stopped`.
- **Sink.** `tools._start_playbook` gives a playbook that takes `tactical` an `HttpSink` with the worker's headers
  (`x-gbox-actor: autoplay`).
- **Panel.** `clients/web/viz/tactical-map.js`:
  - It polls `GET /api/autoplay/tactical/{sid}?after=N` every 125 ms while the section is open and on screen, and
    every 3 s otherwise. The section stays hidden until a frame comes, so other games never see it.
  - It fetches each stage once and keeps it for the page's life.

## Pine Box and the broadcast

Evaluated, not built:

- **Option 1: an overlay page** (`/viz/tactical-overlay.html?sid=…&token=gbb_…`). It would run the same panel code,
  read with a `view` broadcast token, with a transparent background.
  - It costs the Spark nothing, since the viewer draws it.
  - It needs Pine Box to take a browser source.
- **Option 2: `/api/broadcast/tactical/{sid}.mjpg`.** The control plane would draw the same map with PIL, at 5 frames a
  second, only while it is being watched, at nice 10.
  - Pine Box would take it as a second media source and place it picture-in-picture itself.
  - About 5-10 ms of CPU a frame on the Spark.
- **Rejected: compositing the map into the `program` feed.** It would decode, draw and re-encode every program frame
  on the Spark, which is already starved for CPU.

The order of choice is option 1 when Pine Box can show a page, else option 2.

## An overhead camera in the game

Evaluated, not built. RE5 keeps its camera at sBioCamera `0x0191CA6C` +0x104 → uCameraCtrl: eye +0x30, look-at +0x50.
Writing an eye above the player and a look-at on him would show the stage from above, but:

- **The writes are overwritten.** The controller recomputes eye and look-at every frame. Writes from outside the
  process race the game loop at 30 fps and flicker. Making them stick needs a code patch that stops the controller's
  store (an RPCS3 `patch.yml` on the PPU module, applied at boot, never live), with a scratch block for gBox to write.
- **It breaks the bot.** The bot aims along the camera's look ray. An overhead camera would leave it blind, so the
  toggle could only run while the bot isn't aiming, and the aim takes a moment to come back.
- **The view is incomplete.** The game draws for its own camera. Roofs, culling, fog and the HUD were never meant to
  be seen from above, so expect missing geometry and pop-in.

The map above gives the overhead view without any of that.

## Checks

- `tests/test_tactical_map.py`:
  - frames and stages: walls, crossings and climbs; taken bonuses; plans and the fallback; nearest by route;
  - the publisher's rate, stage handshake, back-off and thread;
  - the engine hook; the store; the routes; the HTTP sink; the server install.
- `tests/test_tactical_map.cjs`:
  - words, HUD, view and projection (+x left, heading up), marks and drawing;
  - the feed (after / same / stage once / back-off);
  - the section in a real browser on the real Public Assembly stage, at desktop and phone width.
  - `GBOX_TACTICAL_EVIDENCE=<dir>` keeps its screenshots.
- `tests/fixtures/tactical_map/` holds Public Assembly's stage and 8 frames, read from the Spark's RPCS3 on 2026-10-21
  (read-only, while the RE5 bot played).

### Local RE5 navigation evidence

RE5 (BLUS30491) automatically appends navigation evidence to the worker's existing
`gbox-data/mercs/lessons/BLUS30491/runs/<run>.jsonl`, even without a tactical-map server.
The bot status field `navigation_log` gives the actual path. Files are on the worker
running the emulator; copy the JSONL here for offline analysis if it runs elsewhere.
`local_log_errors` increments if a lesson cannot be written. Logs currently require
manual archival/removal; at two samples per second they grow during long sessions.

Each engine round has a unique `round_id`. `navigation_stage` retains mesh geometry,
walls and crossings once per round/mesh. `navigation_sample` records game coordinates
(including height), facing, target, remaining route, enemies/visibility, timer, prompts,
held inputs and diagnostic reasons at 2 Hz. `before_decision` inputs are the previously
held keys, not the next decision. `navigation_event` bypasses sampling when stuck,
blocked-route, timeout, avoided-crossing or idle-breakout counters increase and includes
the decision's inputs. These are detector events, not proof that every stationary frame
is a collision. QTE-owned frames are sampled too. Missing navmeshes are recorded explicitly.

Generate an offline map and machine-readable event list from the system directory:

```powershell
python -m gbox.mercs.route_trace gbox-data/mercs/lessons/BLUS30491/runs/<run>.jsonl --output route-report
```

Open `route-report/stage-0.svg` (one file per mesh). Gray lines are mesh boundaries,
cyan is actual travel, yellow is planned travel, and red dots are detector events;
hover red dots for the recorded context. `summary.json` retains event details and menu
presses. The SVG is a top-down projection: different floors can overlap; use recorded
Y coordinates to distinguish them. Unknown mesh samples are kept separately.

`navigation_menu` records the RAM screen, sent key, intended stage index and whether
RAM exposed a cursor. Stage choices exclude the immediately preceding intended pick.
The stage cursor is still unverified: its current implementation homes with seven left
presses and moves right to the requested index. A sent press is not proof the game
accepted it. Compare menu evidence with the actual round's mesh to diagnose selection.

This uses existing RAM readers and the game's navmesh. Ghidra is the reverse engineering
source for those readers, not a running visual debugger or a new in-game drawing hook.
The existing tactical map remains the live view; the local evidence supplies history.

RE5 selection now covers original Mercenaries and Reunion: eighteen character/costume
entries across eight stages (144 combinations). A queued explicit selection is retained
until native round-start mode, character and stage agree. A cursor press alone cannot
acknowledge a request. Automatic retry-menu behavior still requires live acceptance.

## Live collection intent and obstruction evidence (2026-10-23)

`POST /api/autoplay/tactical/{sid}/goal` accepts exactly
`{round,stage,kind:"bonus"|"item",id,seq}`, or `{cancel:true}`. An authenticated request
needs a fresh playing frame, a supported entity still present and the current round
and geometry. It accepts no world coordinates, controller buttons or RAM addresses.
The publisher's existing background POST carries the intent back in its reply; only
the engine thread gives it to the current bot. There is no network call on the input
tick and no second input owner. Intents expire after five minutes and reset at round
changes. RE5 supports collection commands; older title adapters remain viewable.

Mandatory prompts, recovery, healing, mine departure and nearby exposed threats keep
priority. Collection uses the existing floor/hazard/traversal planner. A blocked goal
stays visible with its reason. Actor removal alone is `observed_removed`, not proof
of collection. Time pickups additionally need nearby disappearance and a native clock
gain without a concurrent kill. The durable route recorder retains its own stricter
pickup correlation and remains authoritative for round bonus totals.

A stationary route approach now releases movement and replans at the first measured
stall. It saves a bounded nearby native-boundary snapshot, floor, goal and reason to
the navigation learner, trace, and round review. Repeated failures on a directed link
increase its retry delay from 8 to at most 120 seconds; successful observed crossings
weaken the learned failure cost. These are native navigation boundaries and failed
approaches. Solid walls, shipping-container collision and semantic doors/windows
still require their own verified decoders.

The reviewer also retains equipped-item intervals and their observed score, kill and
HP deltas. Counter changes during an interval are observations, not weapon kill
attribution; gaps over two seconds are excluded. The sidebar exposes weapon sections,
operator goals, obstruction evidence and the source-attributed guide profile.
# Map identity audit, 2026-10-30

The live feed now clears the previous floor while a new room has no navmesh,
and clears the renderer's old layout immediately on a stage change. Delayed
responses for a predecessor cannot repaint the current room. Mesh cache keys
include triangle connectivity as well as vertices and triangle count.

Online source checks distinguish reference illustrations from calibrated
geometry. None of these sources supplies a transform into this build's RAM
coordinates; they must not be stretched behind live points and labeled accurate.

| Reference | Confirmed constraint for map work |
| --- | --- |
| [Capcom RE6 stage descriptions](https://news.capcomusa.com/lets/browse/resident-evil-6-pre-order-bonus-mercenaries-maps-detailed) | Rail Yard has multiple levels; High Seas Fortress spans deck and hangars; The Catacombs includes traps. Do not substitute one rail stage for another. |
| [Piggyback RE5 sample map](https://www.piggyback.com/us/wp-content/uploads/sites/6/2020/04/RE5_E_SamplePages.pdf) | Public Assembly illustration is a campaign chapter reference, not a verified Mercenaries spawn/item overlay. |
| [Nintendo Merc3D mission rules](https://www.guiasnintendo.com/0a_NINTENDO_3DS/resident_evil_mercenaries/resident_evil_mercenaries_sp/explicacion.html) | Mission objectives and rank rules differ; Level 1 uses time remaining and EX has different thresholds. |
| [Nintendo Level 5 guide](https://www.guiasnintendo.com/0a_NINTENDO_3DS/resident_evil_mercenaries/resident_evil_mercenaries_sp/mision5.html) | Castle/night, Mines, Ship Deck, Prison and Deserted Island are distinct mission environments. Mines has confined tunnels; Prison has narrow rooms and passages. |
| [Nintendo EX guide](https://www.guiasnintendo.com/0a_NINTENDO_3DS/resident_evil_mercenaries/resident_evil_mercenaries_sp/misionex.html) | Revisited environments can move their items. A stage name alone cannot identify a bonus layout. |

Remaining validation: align each native room/mission identity to its own
geometry, compare at least three non-collinear native landmarks plus floor
height, and record residual error. No claim that every title's level layout
has been calibrated follows from the cache/handover fix.
