# Ghost runs

Inbox #1098 asked to "capture every run that I do in the game and overlay it ... as a speed run versus competitor
that I'm able to retry against and toggle between ... in sync with my person on screen". gBox now records every run
of a supported game from the game's RAM, one sample per emulated frame, and draws earlier runs as translucent
ghosts over the live game, with a race timer and splits.

The game in the request is **Super Mario Bros. (NES)**: catalog `49b6a2f65aca26a2`, "Super Mario Bros. (World)", run
by RetroArch with the Mesen core (session `0a226f781ccb4347-bd3f2df564c54a60` on i9-NUC, World 4-2 in the screenshot).
It is the first game profile. Other dumps of the same game match by platform `nes` and title.

Code: `gbox/ghost_runs.py` (profile, recorder, worker capture, control-plane routes, `ghost_runs` tool) and
`clients/web/viz/ghost-runs.js` (Runs panel and overlay). Tests: `tests/test_ghost_runs.py` and
`tests/test_ghost_runs_ui.cjs`.

## What is recorded

At launch (`tools.launch_game`), a session whose game has a profile starts a recorder on the worker. The reader
thread sends one `READ_CORE_RAM 0 2048` per loop. RetroArch answers in its next frame, so the loop runs at the
emulator's frame rate: about 58 to 60 reads a second and no missed frames (see Verification). It decodes this per
frame:

| field | RAM (SMBDIS label) | meaning |
|---|---|---|
| frame | `$09` FrameCounter | game frames, counted from its deltas (wraps at 256; it stops while the game is paused) |
| x | `$6D` Player_PageLoc, `$86` Player_X_Position | world x = page * 256 + x |
| y | `$B5` Player_Y_HighPos, `$CE` Player_Y_Position | high byte 1 = on screen; y is the top of the 16x32 player box |
| camera | `$71A` ScreenLeft_PageLoc, `$71C` ScreenLeft_X_Pos | the left edge of the screen in world x |
| facing | `$33` PlayerFacingDir | 1 right, 2 left |
| state | `$1D` Player_State | ground, jumping, falling, climbing |
| animation | `$6D5` PlayerGfxOffset | the row of PlayerGraphicsTable being drawn |
| power | `$756` PlayerStatus, `$754` PlayerSize | small / big / fiery |
| inputs | `$6FC` SavedJoypad1Bits | A B Select Start Up Down Left Right |
| level | `$75F` WorldNumber, `$75C` LevelNumber | shown as "4-2" |
| area | `$750` AreaPointer | which map is loaded (main area, bonus room, ...) |
| routine | `$0E` GameEngineSubroutine | 4 flagpole, 5 end of level, 6 lose life, 8 player control, 0x0B death |
| mode | `$770` OperMode, `$772` OperMode_Task | 0 title or demo, 1 game, 2 victory (any castle's axe), 3 game over; task 3 = playing |
| timer | `$7F8..$7FA` GameTimerDisplay | used to detect rewinds |

The addresses are the labels of the doppelganger SMB1 disassembly (SMBDIS, mirrored at
github.com/abnuo/smbdis-dasm). `gbox/smb1_inventory.py` verified its PRG tables against the same source. All of
them were checked live (see Verification).

### Runs, attempts and splits

- **Run**: starts the first time gameplay is seen (OperMode 1 with task 3), normally on 1-1 after Start. The attract
  demo (OperMode 0) never starts one. A run ends as one of these:
  - `complete`: the axe of world 8.
  - `game_over`.
  - `reset`: back to the title.
  - `state_loaded`: the level changed while the player was in control, which means a save state of another level was
    loaded. A new practice run starts from there.
  - `session_end`: the game was stopped.
  Runs with less than 30 frames of gameplay are dropped.
- **Attempt**: one try at a level. It runs from the first gameplay frame after the level or lives screen to one of
  these:
  - `clear`: the flagpole, a castle's axe, or a warp pipe.
  - `death`: routine 6 or 0x0B.
  - `end`: the run ended.
- **Split** per cleared level: from the first try's start to the clearing try's end, deaths included. `segment` is the
  clearing try alone.
- **Rewinds**: RetroArch rewind, gBox's checkpoint ring, or a state of the same level all push the level timer back
  up while the player is in control. When that happens the frames that were undone are dropped, so the ghost shows
  what actually counted, and the run is marked `assisted`. Assisted runs are kept and shown, but they are never best.

### Storage

The control plane keeps these:

- `ghost_run` docs: metadata, splits and attempts.
- `ghost_track` docs: the per-frame track as zlib + base64 of 18-byte rows (`f x y lv ap face st anim pw joy scr
  sub`, format `smb1.v1`), about 35 KB per minute of play (measured on a real 1-1 trace).
- `ghost_prefs` docs, one per game: the ghost choice, colours, sync mode, HUD and picture settings.

`annotate()` sets these flags:

- `best`: the fastest complete run per category. The category is the start level, plus assisted or not.
- `best_progress`: where no run of a category is complete, the run that got furthest, fastest.
- `level_bests`: the fastest clearing segment per level, from runs that are not assisted.

## The overlay

`ghost-runs.js` puts a click-through canvas over the game picture. The picture can be the streamed `<img id=scr>` or
the GPU compositor's `<video>` in `#nativeslot`.

- **Projection, not injection.** A ghost's screen x is its recorded world x minus the *live* camera
  (ScreenLeft). That is the same subtraction the game uses for Player_Rel_XPos. Its y is the recorded screen y: SMB1
  never scrolls vertically. A small player is drawn in the lower half of the 16x32 box, one line down (OAM y + 1).
  The live check is below. Injecting a ghost actor into SMB1 is not possible without a ROM patch, because the game
  rewrites every object slot and all 64 OAM entries each frame. Profiles for games with known actor spawning
  (SM64 / OoT) could inject one later. `Profile.public()["injection"]` says why not here.
- **Sync** has two modes:
  - Level (default): each ghost is as far into your current level as you are. It uses the ghost's clearing try, or
    its longest try on that level if it never cleared it.
  - Run: the same frame since the run started. The ghost is drawn only while it is on your level and map.
  If a ghost is in another room or level, the HUD says where. If it is off screen, an edge arrow shows its distance
  in blocks.
- **Timing**: the worker posts the live player state (level, level and run frame, camera, your box) about 10 to 15
  times a second, on its own sender thread (median 4 ms per post). The overlay polls it every 66 ms and
  extrapolates frames and camera between updates, so ghosts move at the display rate.
- **Picture mapping**: native 256x240 pixels are mapped onto the frame through the emulator's aspect. The options are
  4:3, 8:7 pixels (1.219, Mesen's own aspect), square pixels, fill, and Auto. Auto scores each candidate by how much
  the predicted box around your player stands out from its surroundings, and decides only with a clear margin. The
  default is 4:3, measured on the operator's #1098 screenshot: on i9-NUC the 4-2 ceiling and floor sit at native
  lines 32 and 208 at 2.81 px per line. On this PC the same RetroArch config shows 8:7 (1.219). Tick **Me** to
  outline your own player and check the alignment.
- **Picture-in-picture and full screen** in the desktop app draw the game in the app window itself, outside the session
  page, and show no ghosts.
- **Docked native window**: when the game is docked as a native window (not the GPU compositor), nothing can be
  drawn over it. The panel says to turn on the GPU compositor. Recording works either way.

## The Runs panel

The Runs panel sits in the session sidebar, next to Controller and Session, and can be docked like them.

- **Status**: whether a run is recording, its level and time, deaths, and the assisted flag.
- **Ghosts**: Best, Last N (click again to cycle N from 1 to 5), Best levels (for each level, the run with its
  fastest segment), Picked (the ticked runs, stacked), or Off.
- **Sync**: Level or Run. **Timer** turns the race HUD on or off: your run and level time, and each finished split
  against the lead ghost (green when you are ahead, red when behind). **Me** outlines your own player. The
  **Picture** list sets the aspect.
- **Each run**: a show/hide tick, a colour, its number and name (✎ or a double-click renames it), a best or furthest
  badge, the time, start to end level, the outcome, deaths, the date, and its splits (the split, the segment, a ★ on
  the best segment of each level). 🗑 deletes it; click it twice to confirm.

## API

| method | path | |
|---|---|---|
| POST | `/api/ghosts/live/{sid}` | worker: the live player state (`{"on": false, "ended": true}` at the end) |
| GET | `/api/ghosts/live/{sid}` | overlay: the live state (`on: false` after 5 s without news) |
| POST | `/api/ghosts/runs` | worker: a finished run with its packed track |
| GET | `/api/ghosts/game/{gid}` | runs (newest first, flags, numbers, colours), `level_bests`, `prefs`, `showing`, `profile` |
| GET | `/api/ghosts/runs/{rid}` | one run with its track as columns |
| PATCH | `/api/ghosts/runs/{rid}` | `{"name": ...}` |
| DELETE | `/api/ghosts/runs/{rid}` | deletes the run and its track, and removes it from the picks |
| POST | `/api/ghosts/game/{gid}/prefs` | `pick`, `shown`, `colors` (merged), `mode`, `last_n`, `hud`, `me`, `picture` |

## Agents

The `ghost_runs` registry tool (MCP: `job_ghost_runs`, local agent: `ghost_runs`) has these ops:

- `profiles`
- `status session_id` (the live recorder on the session's worker: reads, reads/s, posts, the run in progress)
- `list game_id`
- `show run_id`
- `rename run_id name`
- `delete run_id`
- `pick game_id pick=... [runs] [mode]`

## Verification (2026-10-13)

This used an isolated RetroArch 1.22.2 with the Mesen core on JAYBUILTFINALE. It had its own config and user folder
in the agent scratchpad, its window off screen, `input_driver = "null"` so no physical pad reached it, and a private
network pad on its own port. The operator's sessions were not touched, and no game file is in the repo.

- `READ_CORE_MEMORY` answers at most 256 bytes per request on Mesen. `READ_CORE_RAM 0 2048` (the RetroAchievements
  view, internal RAM at $0) answers the whole 2 KiB in one round trip, so the recorder uses it and falls back to
  256-byte `read_memory` calls on other adapters.
- A tight read loop saw every frame: 60.5 reads/s and FrameCounter gaps of 1. The recorder loop does 55 to 58
  reads/s with gaps of 0 or 1, and it was the same with a second reader on the port. An early version slept
  between reads and fell to 42/s with 2 to 3 frame gaps, and to 8/s with synchronous posts. Both were fixed.
- Projection: on 2857 gameplay frames of 1-1, `Player_Rel_XPos == (world x - ScreenLeft) mod 256` on every frame
  with the player in control. With the emulator paused, the box predicted from RAM (`relx`, `rely + 1`, small player
  in the lower half) enclosed Mario exactly on a GPU screenshot.
- Routines: Start leaves OperMode 0 for 1. The attract demo runs in OperMode 0 with task 3. A goomba death was
  routine 0x0B, a pit death 6 with Y_HighPos 6, and the flagpole 4. FrameCounter stands still while the game is
  paused.
- A scripted 1-1 run (a network pad holding right and B, jumping, with the star timer refreshed) was cut correctly:
  a death attempt, then a clear attempt at the flagpole, with a 1-1 split of 3096 frames (segment 2074, 1 death).
- End to end, the real `Capture` posted to a local control plane with these routes:
  - Run A ended `game_over` with 3 deaths and was stored.
  - During run B the live state reached the server at 9.8 posts/s (median latency 4.4 ms).
  - At a paused frame of run B, run A's ghost, as far into 1-1 as run B, was projected onto the GPU screenshot next to
    the live Mario, mid-jump over the pipe it jumped in run A.

## Tests and screenshots

```
python -m pytest tests/test_ghost_runs.py          # synthetic RAM traces: decoding, runs, rewinds, routes, capture
node --test tests/test_ghost_runs_ui.cjs           # sync, sampling, projection, picture mapping, race rows, Auto
python scripts/ui_evidence.py --clients clients --fixtures tests/fixtures/ui_evidence/ghost_runs.json --out <dir>
```

The fixture's runs were made by the Recorder from synthetic traces. Its game picture is a plain SVG drawing.

## Adding a game

Add a `Profile` to `PROFILES` with these parts:

- the game ids and a title pattern;
- the RAM block to read;
- a decoder to the sample fields above;
- the native picture size and player box.

The recorder's run and level rules (OperMode, routines) are SMB1's. A game with other rules needs its own feed
logic. A 3D game also needs its camera matrix from RAM for the projection, as `pick_identify` / `mgs_vr` use.
