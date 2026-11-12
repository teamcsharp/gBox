# Round 292: why that title screen cannot be driven - and the one action that fixes it

## What the operator is looking at

A **headless co-op session** (`bcd14c8d972940b2-c25969f531a04870`, process `gBox Dolphin.exe -b`) at the attract loop. gBox displays its framebuffer
inside the PiP, so it looks like a normal game - but the emulator was started with **`-b` batch mode: it has no window at all**.

## Everything tried on it, and what each proved

| attempt | result |
|---|---|
| `autoplay start` with `pso-boot-from-title-a` | **refused**: `{"already_running": "vision: make progress"}` |
| stop it, then start the deterministic mission | **started, then failed every step**: `"no player in semantic state"` - there is no character yet, which is exactly what the mission was supposed to create |
| `session_op send_input` with START/A events | **job succeeds, game does not react** - the adapter's Windows path falls back to `win_send_keys(pid)` for whatever the network gamepad could not carry, and a headless process has no window to send to |
| `session_op send_input_player` | **refused**: `op send_input_player not allowed via session_op` |
| `autoplay start` with `campaign: pso-coop-episodes-1-2` | **failed**: `PSO route planner model 'qwen2.5vl:7b' is not available` |
| `ollama pull qwen2.5vl:7b` | **refused**: the ollama **server** is too old and answers "Please download the latest version", so no new model can be installed; only `deepseek-r1:14b` and `8b` exist, and those are text-only |
| LM Studio as an alternative vision backend | its daemon will not start and it has **no models on disk** |

So the session is at a title screen whose input path does not exist: the co-op stack's virtual pads were configured by `pso_coop_setup` for the plane's
own bot, the keyboard path needs a window, and the campaign that would drive the menus needs a vision model that cannot be installed on this machine.

## The action that fixes it

**Close that game and launch PSO again from the gBox app.**

A game launched from the app is **operator-owned**, and on such a session the keyboard path works - that is how the Dragon was fought, the floor
changed nine times, and hundreds of units were walked in this session. An agent-launched session is `agent_owned`, and no input reaches it: that is
the trap the co-op launch walked into.

**Then press F3.** `f3_takeover.py` is armed and running: F3 takes the screen and starts playing immediately, F3 again stops. That is the mode the
operator asked for, and it needs an operator-owned game to act on.

## What was learned that is worth keeping

* `autoplay` drives the game **through the session's debugger**, not the keyboard - the right tool for a session without a window, when its model
  requirements are met;
* the plane has **named deterministic PSO missions** (`pso-boot-from-title-a`, `pso-gc-forest1-first-wave`) that need no model, but the boot one
  assumes a character already exists;
* **jobs dispatch** with `require_worker` + `agent_use: false`, which is how all of the above was even testable;
* `pso_campaign` runs a real two-player campaign (`pso-coop-episodes-1-2`) and its only missing piece here is the vision model.

## State

| item | state |
|---|---|
| headless co-op session | at the attract loop, **undrivable**; autoplay stopped |
| F3 takeover | **armed and running** |
| operator game | not running |
| vision model | not installable (ollama server too old) |
| everything else | maps for 14 floors, play loop, weapon advisor, mod icons, minimap, click-to-order |
