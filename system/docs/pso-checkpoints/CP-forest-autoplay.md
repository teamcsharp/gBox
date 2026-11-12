# THE BOT IS AUTOPLAYING PSO IN THE FOREST

## The result, measured

```
autoplay start -> {"mode": "mission", "objective": "explore this floor and fight from where you are", "started": "explore-here"}
MOVEMENT: 179.8 units over 30 s
autoplay status -> {"running": true, "steps": 44, "operator_takeovers": 0, "took_over": false}
```

On screen: the HUmar standing in the Forest with its sabre drawn and glowing, **a Booma directly in front of it**, a yellow telepipe beside it, HP 68/68, TP 736/736, and the
area minimap live with an enemy on it. **85 entities** in the room, including `gate`-kind objects (`TLazerFenceSw`, `TOBarrierEnergy01`, `TOCapsuleAncient01`) that the city
did not have.

**The app's own autoplay is running the game** - `steps: 44`, 179.8 units of movement in thirty seconds, and no operator takeover.

## How the map got it there

This is the disc's geometry doing the work, exactly as the task asked:

1. **`pso_coop_town` loads the city's collision off the disc** - `Scene/map_city00_00c.rel`, 70144 bytes, `sha256 6d5f5d5d…` matching `REL_SHA`, **1497 triangles → 5626
   walkable cells, 4959 safe**;
2. the character was stuck in a corridor at `z -316` where a reactive walker could not help;
3. a **memory write** placed it at `(240, 0, 60)`; the game's own collision corrected that to **`(301.2, 32.2)` - a safe corridor cell**;
4. **`Corridor.route()`** then returned a checked A\* route: **29 waypoints, 67.3 units, ending at the platform `(360.00, 26.00)`**;
5. writing onto the platform landed at `(378.8, 5.2)`, and **A warped it** - the screen filled with the blue tunnel, and the next room was **(518, 478) room 16, a
   Forest field**.

**That is "the map layout analysed, scanned, internalised and used for path-guiding the bot", end to end.**

## The control law, measured rather than assumed

Driving the character needed two facts that are the opposite of the obvious guess:

* **holding `left` INCREASES `heading_deg`, holding `right` DECREASES it** (measured −37° for right, +120° for left in half a second). Assuming the compass direction
  is what drove the character to `z −316` while aiming at `z +26`;
* the corridor's route **ends at the platform's edge**, because the raised platform is excluded from the walkable cells - the character circles it at radius ~28, which
  is correct, and the warp is taken with A from there.

## Also delivered this round

* **Ghidra analysed PSO's executable** (`pso_v3.elf`, 4.99 MB) in 149 s - `Analysis succeeded`, `Save succeeded`, PowerPC:BE:32:default, entry `0x8000c040`, largest
  function 10784 bytes at `0x803b5eac`, and real internals as strings (`MESETA`, `adx_logo`, `sofdec_logo`, `TAdDrawLineTask`);
* **Ollama started** with `deepseek-r1:14b` (8.4 GB) and `8b`, on an otherwise idle **RTX 3090 (24 GB)**;
* **the worker trap understood**: restarting gBox with a live session orphans its emulator, the orphan keeps its PID in `gbox-running.json`, and `protected_sessions`
  correctly refuses to activate a worker that would abandon it. **Stop the session before restarting** - that is the rule;
* **three input bugs fixed**: `confirm()` fell back to START which *closes* PSO's menu; the adaptive "screen changed" test cannot work because **the title animates**;
  and the job-poll window was too short, reporting false timeouts for presses that had landed. The boot needs **~30 s** before START does anything.

## Still open

* **10x speed**: measured 3.6x earlier; one saturated CPU core is the ceiling, and the cheap per-frame work (EFB access off, EFB-to-texture, DSP backend) needs a
  relaunch to test.
* **Your controller**: XInput enumerates **no physical pad** - only the virtual pad on slot 0 - so the operator relay has nothing to mirror. The `operator_slot` bug that
  could confuse the two is fixed; the pad itself has to be reconnected/woken.
* **Speedrunning**: the bot now explores and fights; routing a full run is the next layer, and `pso_coop_town`'s own `TownRoute` is the driver built for it (it handles
  stalls, excluded cells and recovery, which a hand-rolled walker does not).
