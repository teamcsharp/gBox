# The inverted cast in MercMode: what works, what does not yet

2026-11-06. The operator wants the RE titles playing with swapped skins "from here on out", the zombies wearing cast
models, the player wearing majini clothes. This records what is proven and the two scheduler gaps that still stop it
happening on every launch without help.

## Proven

* **The build works and the round plays.** `skin_swap.cast_swap_build` produced uEm6c -> sheva (2 meshes, 27 textures),
  uEm71 -> wesker (2 meshes, 21 textures), rebecca wearing majini clothes (pl1d_03Body <- em6c00_00, retagged) and
  excella <- josh; launching that build reached `screen=playing` with the HUD live (score 000900, 03'24"74, combo 003)
  and the frame showed Rebecca in the majini outfit with a cast figure in the doorway.
* **The settings stick.** lilspark: titles `['re5']`, skin_swap `random`, cast_swap `on`, source `this_control_plane`.
* **The edition resolves correctly when the rotation picks.** The inventory row for re5 reads
  `map_id=010018100CD46000 game_id=52d15709be0fda1a platform=switch playable=True`, i.e. the Switch No Mercy edition
  named by `preferred_editions`.
* **The scheduler does launch on its own** once nothing is blocking it: after a stale 9-hour operator dispatch was
  replaced, it launched within a minute and reported `playing Resident Evil 5 - Gold Edition`.

## Gap 1: a dispatched start launches the native edition, not the preferred one

Every autonomously launched round so far came up as game id **`e7ca89bbeb67360d`** - the **PS3** RE5
(`TITLES['re5']['game_ids']`), not the Switch `52d15709be0fda1a`. Since `cast_swap_build` and `random_swap_build` are
keyed on the Switch title id (`010018100CD46000`) and its romfs arcs, a PS3 round cannot be swapped at all, which is why
**no `mercmode.cast_swap` audit was written by the scheduler** even though the setting was on. The dispatched launch
path does not consult `preferred_editions` the way `choose()` does; that is the thing to fix before the cast can be
called automatic.

## Gap 2: the rotation stalls after a session is ended by hand

After ending a session through the API, the scheduler sat at `scheduler_note: "ended: the game ended"` for 25 minutes
with `enabled: True`, no live session and `preferred_editions` correct, and only launched again after a fresh
stop -> start dispatch. Ending a session by hand is not the normal path (a round ends itself), but the stall is real and
will also hit an operator pressing Stop.

## Also fixed while here

* `MercModeIn` now accepts `cast_swap`: without it every configure to a host with a local scheduler returned **422**
  (`extra_forbidden`), because the setting relayed fine but the worker's input model rejected the job.
* `cast_swap` and `skin_swap` now travel with worker feature flags (`mercmode_cast_swap`, `mercmode_skin_swap`) and
  workers advertise both, so an older worker is never sent a setting its tool would reject. `skin_swap` had been relayed
  ungated since it was added, which is what `test_central_settings_delegate_once_and_manual_prepare_tracks_exact_job`
  was catching.
* The RE5 select calibration no longer raises its press budget: the target stays reachable inside `CYCLE_MAX_PRESSES`,
  so a locked entry is still given up at 14 presses and a long roster takes a few visits instead of one.
