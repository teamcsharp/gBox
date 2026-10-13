# Rewind and fast-forward in every game

Hold **Select + L2** to rewind and **Select + R2** to fast-forward, on the operator's own pad, in every game gBox runs
(tickets #454 and #1382). Select is the modifier, so L2 and R2 keep working normally in games that use the triggers.
Code: `gbox/rewind.py`; the hook points are `tools._launch_game` (start), `tools._pump` (streamed pad events),
`tools.session_op` (the `rewind` op, the save/load guard, stop).

Which kind of rewind a session has is in its capabilities (`launch_game` output, `GET /api/sessions`, the `info`
session RPC): `rewind = "native" | "checkpoint" | "unsupported" | "off"`. `detail.rewind` carries the settings
(interval, depth) and the ring's live status.

| Kind | Where | How Select+L2 works | Select+R2 |
|---|---|---|---|
| `native` | RetroArch cores with rewind on (8/16-bit, N64, PSX, PSP, ...) | RetroArch's own rewind buffer. Windows: its hotkeys (Select is the enabler, `input_enable_hotkey_btn = 4`, `input_rewind_axis = +4`). Streamed: its hotkeys where the game leaves the triggers free (`trigger_hotkeys`), else the worker sends `REWIND` steps over the command port on each press / repeat | the worker's ramp; streamed sessions with the hotkeys use RetroArch's own hold-fast-forward instead |
| `checkpoint` | RetroArch heavy cores where rewind would stutter (`adapters.NO_REWIND`: Flycast Dreamcast/Naomi, PCSX2, Citra, the Dolphin core, ...) and standalone Dolphin (Windows and the Spark's flatpak) | gBox's checkpoint ring: a save state every 2 s; each press loads the next older one, holding repeats every 0.6 s | the worker's ramp through the adapter's `fast_forward` (RetroArch's toggle; Dolphin's Tab = speed limit off) |
| `unsupported` | Xenia, Yuzu (no save state gBox can trigger), RPCS3 (its save state reloads the game), Steam | nothing | nothing |
| `off` | checkpoint sessions with `[rewind] checkpoints = false` or `launch_game` `rewind = false` | nothing | the ramp still works |

## The fast-forward ramp

The same ramp everywhere (`rewind.FastForwardRamp`, the one RetroArch sessions had before): 2x for the first 1.5 s
of holding, 4x until 3.5 s, then 16x. Emulators run fast-forward at one fixed ratio (RetroArch: `fastforward_ratio
= 16`; Dolphin: unlimited), so the lower speeds come from switching it on for part of the 60 Hz ticks.

## The checkpoint ring

`rewind.CheckpointRing`, one per checkpoint session, files under `<runtime>/rewind/<session id>/` (deleted when the
session ends; rings of a previous worker run are swept at the next launch).

- A checkpoint is taken through the adapter's own save-state mechanism every `interval_s` (default 2 s), at most
  `depth` (60) entries and `max_mb` (2048) on disk; the oldest go first. Nothing is taken while a save or load is in
  flight: the ring's own, the operator's (`session_op save_state / load_state`) or a session swap (`state_transfer`).
  A failed save backs the ring off (doubling, up to 30 s) and is reported in `detail.rewind.error`.
- RetroArch (`checkpoint_state = "path"`) saves to the operator's current slot. The ring copies the operator's slot
  file aside before its first save and puts it back after every one of its saves and loads, so what is on disk in
  the slot stays the operator's own save; the operator's manual save / load / session swap work as before.
- Dolphin (`checkpoint_state = "dir"`) saves the ring in its slot 8 (`Shift+F8` / `F8`), found as the fresh file
  under `User/StateSaves`; the operator keeps slot 1.
- Holding the chord freezes the ring; stepping walks from the newest entry to the oldest. Letting go drops the
  entries newer than the one loaded (that future was undone, like RetroArch's own rewind) and the ring resumes.
- `session_op op=rewind args={"seconds": N}` does the same from the API and the agent (N / interval steps).

## Settings

`gbox.toml`:

```toml
[rewind]
checkpoints = true     # false: emulators without a native rewind get none (RetroArch's own is unaffected)
interval_s = 2.0       # seconds between checkpoints
max_duty = 0.05        # frame-rate budget: slow saves stretch the interval
depth = 60             # checkpoints kept per session
max_mb = 2048          # disk cap per session's ring
repeat_s = 0.6         # holding Select+L2: one older checkpoint per repeat
```

Per session: `launch_game` input `rewind = true | false` overrides `checkpoints` for that launch.

## How the chord is read

gBox never intercepts the pad; it watches it.

- Windows (local native windows): the worker polls XInput slot 0 at 60 Hz (`rewind.XInputPad`): Back/View = Select,
  the triggers above 60/255 = L2/R2. This is what the RetroArch ramp used before.
- Streamed sessions (the Spark): the browser's Gamepad API events pass through the worker's input loop
  (`/api/sessions/{sid}/input` -> `_pump.inputs`) and are fed to the detector there (`rewind.feed`).
- Gap: a pad plugged into the Linux node itself is not read (no evdev dependency; the Spark's games are played
  through the stream).

## Limits

- A checkpoint is a full save state: RetroArch's Flycast states are about 27 MB, PCSX2 and Dolphin states tens of
  MB. At the default interval that is one such write every 2 s and up to `max_mb` on the local disk; a brief hitch
  per save is possible on the heaviest cores (raise `interval_s` for those).
- Frame-rate budget (#1489): the ring times every save and stretches its interval so saving takes at most
  `max_duty` (default 0.05 = 5 %) of play time, capped at one checkpoint per 120 s; a 1 s save means one checkpoint
  every 20 s. Flycast (Dreamcast / NAOMI / Atomiswave) has a 20 s floor regardless: its ~27 MB states at 2 s dropped
  PSO to 2 fps. The live status reports `effective_interval_s` and `last_save_s`. `max_duty = 0` disables the pacing.
- Step granularity is the interval (2 s), not frames; the first press goes back up to 2 s.
- Dolphin's hotkeys are sent as keystrokes into its window (`win_send_keys`), which needs gBox to be the active
  window and moves keyboard focus to the game. Dolphin checkpoints are therefore taken only while the operator's pad
  is in use (`checkpoint_when_playing`: pad activity within the last 3 s); a long idle cutscene has no checkpoints,
  and while the operator is in another app the ring pauses and backs off.
- The on-screen "Saved state to slot 8" message Dolphin shows on each checkpoint can be turned off in Dolphin's
  interface settings (OSD messages).
- RPCS3 has no in-place save state (F2 saves and reloads the game), so PS3 sessions report `unsupported`.
