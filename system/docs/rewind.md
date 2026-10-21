# Rewind and fast-forward in every game

Hold **Select + Left/Down or L2** to rewind and **Select + Right/Up or R2** to fast-forward. The same chords are
recognized for every emulator; capabilities state which actions the emulator can actually perform. Select is the
modifier, so standalone directions and triggers remain game controls. On the focused GPU game surface, Right Shift
is Select, the arrow keys are directions, E is L2, and R is R2.
Code: `gbox/rewind.py`; the hook points are `tools._launch_game` (start), `tools._pump` (streamed pad events),
`tools.session_op` (the `rewind` op, the save/load guard, stop).

Which kind of rewind a session has is in its capabilities (`launch_game` output, `GET /api/sessions`, the `info`
session RPC): `rewind = "native" | "checkpoint" | "unsupported" | "off"`. `detail.rewind` carries the settings
(interval, depth) and the ring's live status.

| Kind | Where | How Select+L2 works | Select+R2 |
|---|---|---|---|
| `native` | RetroArch cores with rewind on (8/16-bit, N64, PSX, PSP, ...) | The worker sends `REWIND` steps through RetroArch's command channel on each press / repeat. Conflicting native time hotkeys are disabled to avoid double execution | the worker's ramp |
| `checkpoint` | RetroArch heavy cores where rewind would stutter (`adapters.NO_REWIND`: Flycast Dreamcast/Naomi, PCSX2, Citra, the Dolphin core, ...) and standalone Dolphin (Windows and the Spark's flatpak) | gBox's checkpoint ring: a save state every 2 s; each press loads the next older one, holding repeats every 0.6 s | the worker's ramp through the adapter's `fast_forward` (RetroArch's toggle; Dolphin's Tab = speed limit off) |
| `unsupported` | Xenia, Yuzu (no save state gBox can trigger), RPCS3 (its save state reloads the game), Steam; standalone adapters without verified state-file discovery | the session reports the concrete reason; no fake rewind success | the session reports whether it has a verified speed-control interface |
| `off` | checkpoint sessions with `[rewind] checkpoints = false` or `launch_game` `rewind = false` | nothing | the ramp still works |

## The fast-forward ramp

The shared ramp (`rewind.FastForwardRamp`) targets 2x for the first 1.5 s of holding, 4x until 3.5 s, then the top
speed. It pulses fast-forward over 60 Hz ticks. RetroArch uses `fastforward_ratio = 16`; Dolphin holds its unlimited
speed key, so its actual rate depends on hardware and game load and is not an exact multiplier. Releasing the chord,
unplugging its controller, or ending the session releases the speed key. Rewind takes priority if both directions
are held. Dolphin's Windows speed keys use the same background-safe F13–F15 lanes as its existing state hotkeys.

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
  When the slot changes (an operator or emulation-issue save to slot 15, #1488), the ring follows it: the old slot
  file is given back, the new one (`RetroArchAdapter.checkpoint_target()`) is protected before the ring's next save,
  and a save that lands in an unprotected slot never receives another slot's backup.
- Dolphin (`checkpoint_state = "dir"`) saves the ring in its slot 8 (`Shift+F8` / `F8`), found as the fresh file
  under `User/StateSaves`; the operator keeps slot 1. Slot 10 belongs to demo jump states (`gbox/jumpstate.py`):
  saved only (`Shift+F10` on the Spark, the all-modifier lane chord on Windows), copied to `runtime/jumpstates` and
  removed; a demo launch boots straight into one with Dolphin's `--save_state`, so no key ever loads slot 10.
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

- Windows (local native windows): the worker polls a connected XInput slot at 60 Hz (`rewind.XInputPad`):
  Back/View = Select, the triggers above 60/255 = L2/R2, and the D-pad provides direction aliases. The same pad
  remains selected until it disconnects; a reconnected pad in another slot is discovered automatically.
- Streamed sessions (the Spark): the browser's Gamepad API events pass through the worker's input loop
  (`/api/sessions/{sid}/input` -> `_pump.inputs`) and are fed to the detector there (`rewind.feed`).
- Streamed time chords are removed before game input is injected. If a direction/trigger already reached the game
  before Select joined, gBox sends its release on chord entry. A swallowed key stays swallowed until physically
  released, preventing a stray weapon/menu action when Select is released first. Player 2 is never a time modifier.
- Native physical controllers are watched rather than intercepted: their game may still see their physical buttons.
  This change does not install a global controller filter or replace emulator controller bindings.
- Gap: a pad plugged into the Linux node itself is not read (no evdev dependency; the Spark's games are played
  through the stream).

## Limits

- A checkpoint is a full save state: RetroArch's Flycast states are about 27 MB, PCSX2 and Dolphin states tens of
  MB. At the default interval that is one such write every 2 s and up to `max_mb` on the local disk; a brief hitch
  per save is possible on the heaviest cores (raise `interval_s` for those).
- Frame-rate budget (#1489): the ring times every save and stretches its interval so saving takes at most
  `max_duty` (default 0.05 = 5 %) of play time, capped at one checkpoint per 120 s; a 1 s save means one checkpoint
  every 20 s. Flycast (Dreamcast / NAOMI / Atomiswave) has a 20 s floor regardless: a full Flycast state every 2 s
  dropped PSO to 2 fps. The live status reports `effective_interval_s` and `last_save_s`. `max_duty = 0` disables the pacing.
  Measured on the Spark (RetroArch Flycast, PSO Ver. 2 title screen, GL on the GB10): each checkpoint stalls the
  game 0.38-0.57 s for a ~9 MB state, so the old 2 s pacing spent up to 29 % of play time saving; at the 20 s floor
  it is 2.9 %. `tests/test_rewind_flycast_live.py` repeats that check on a real disc (opt-in:
  `GBOX_FLYCAST_LIVE_ROM=<disc.chd>`; it writes only to a scratch runtime).
- Step granularity is the interval (2 s), not frames; the first press goes back up to 2 s.
- Dolphin's Windows checkpoint and speed hotkeys use background-safe reserved keys without moving focus.
  Checkpoints are taken only while the operator's pad
  is in use (`checkpoint_when_playing`: pad activity within the last 3 s); a long idle cutscene has no checkpoints,
  and while the operator is in another app the ring pauses and backs off.
- Linux Dolphin writes explicit hotkey bindings on its own Xvfb display and discovers checkpoints under the actual
  `-u` user directory. Replay/test adapters can select a private `gameplay_demo_user`; all configs and StateSaves
  follow that folder rather than the operator's normal Dolphin profile.
- The on-screen "Saved state to slot 8" message Dolphin shows on each checkpoint can be turned off in Dolphin's
  interface settings (OSD messages).
- RPCS3 has no in-place save state (F2 saves and reloads the game), so PS3 sessions report `unsupported`.

Dolphin's held speed-limit action and state-slot labels follow its
[upstream hotkey implementation](https://github.com/dolphin-emu/dolphin/blob/master/Source/Core/Core/HotkeyManager.cpp).
