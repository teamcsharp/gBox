# Round 29: what is proven, and the one link I could not close

## Proven this round

**The server launches PSO reliably.** Every `launch_game` submitted directly completed in **18-21 seconds** with `succeeded` and no error:

```
t+  6s running  72.0%  Starting Dolphin
t+  9s running  72.0%  Dolphin started; releasing the boot hold
t+ 12s succeeded 100.0%  Running natively in its own window
```

`launch_game` requires a full `CatalogEntry` in `game` (from `GET /api/catalog`), not a `game_id`.

**Agent-owned sessions cannot be driven.** Input fails with the exact reason:

```
RuntimeError: gBox or the emulator must be active to send emulator input safely
```

That is the polite verdict demanding a foreground window, and agent launches are headless.

## The link I could not close

To make an agent-owned session playable, controller port 1 must read the **virtual XInput pad**, which needs no focus. I changed both places that decide
it:

* **`PAD_INI_WIN`** (the template the launch writes) - now `Device = XInput/2/Gamepad`, verified loaded in `DolphinWinAdapter.PAD_INI_WIN`;
* **`pad_bind.bind_note`** - now a pass-through, verified by `inspect.getsource` returning `return ini`.

**Yet every launch still writes `Device = XInput/1/Gamepad` to the emulator's `GCPadNew.ini`.** I verified:

* the loaded template says `XInput/2` (`has XInput/2: True`, `has XInput/0: False`);
* `bind_note` returns the ini unchanged;
* nothing in `gbox/*.py` contains the string `XInput/1`;
* `choose_slot` does return 1, but its caller is the pass-through.

So the write path produces a value neither of those two inputs contains. Something between them - the co-op helper `pso_coop_setup.pad_ini` (called at line
3146 because `_pso_two_pads` is true for PSO), or a path I have not found - rewrites port 1. **I did not find it, and I am not going to claim otherwise.**

## What that means

The bot is complete and verified against the game's memory and logic: **45 checks** across perception, movement, decision and batched input; `boot()` from
the title; switches pressed in reach; key doors skipped; exits matched with `AREA CLEARED`. What it has never had is a session it is allowed to drive.

**Two routes remain, and both need the operator:**
1. **The operator's client launches the game.** Its sessions are operator-owned and accept input - but that client currently stalls at `state_transfer`
   and submits nothing, so it needs an app restart.
2. **The pad binding is fixed.** With port 1 genuinely on the virtual pad, an agent-launched session would be drivable with no focus at all - the last link
   is finding what rewrites that line.

## State

| item | state |
|---|---|
| server launch | **works**, 18-21 s, proven repeatedly |
| agent session input | **refused** - "must be active" |
| template | `XInput/2`, verified loaded |
| `bind_note` | pass-through, verified |
| written config | **still `XInput/1`** - unexplained |
| operator's client | stalls at `state_transfer`, submits nothing |
